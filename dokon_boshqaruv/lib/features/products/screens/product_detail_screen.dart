import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/products_provider.dart';
import '../models/product.dart';
import '../../../src/app.dart'; // Import for apiProvider
import 'edit_product_screen.dart';

class ProductDetailScreen extends ConsumerWidget {
  final int productId;

  const ProductDetailScreen({super.key, required this.productId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final productAsync = ref.watch(productProvider(productId));

    return Scaffold(
      appBar: AppBar(
        title: const Text('Mahsulot ma\'lumotlari'),
        actions: [
          IconButton(
            icon: const Icon(Icons.edit),
            onPressed: () {
              productAsync.whenData((product) {
                if (product != null) {
                  Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => EditProductScreen(product: product),
                    ),
                  );
                }
              });
            },
            tooltip: 'Tahrirlash',
          ),
          IconButton(
            icon: const Icon(Icons.more_vert),
            onPressed: () => _showOptionsMenu(context, ref),
          ),
        ],
      ),
      body: productAsync.when(
        data: (product) {
          if (product == null) {
            return const Center(
              child: Text('Mahsulot topilmadi'),
            );
          }

          return SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Product Image
                Container(
                  height: 250,
                  color: Colors.grey[200],
                  child: product.image == null || product.image!.isEmpty
                      ? const Center(
                          child:
                              Icon(Icons.image, size: 80, color: Colors.grey))
                      : Image.network(product.image!,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => const Center(
                              child: Icon(Icons.image,
                                  size: 80, color: Colors.grey))),
                ),

                // Product Info
                Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Name and Status
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Text(
                              product.name,
                              style: const TextStyle(
                                fontSize: 24,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                          _buildStockStatusBadge(product),
                        ],
                      ),

                      const SizedBox(height: 8),

                      if (product.categoryName != null)
                        Chip(
                          avatar: const Icon(Icons.category, size: 16),
                          label: Text(product.categoryName!),
                          visualDensity: VisualDensity.compact,
                        ),

                      const SizedBox(height: 24),

                      // Price Cards
                      Row(
                        children: [
                          Expanded(
                            child: _InfoCard(
                              title: 'Sotuv narxi',
                              value: '${product.salePrice} UZS',
                              icon: Icons.sell,
                              color: Colors.green,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: _InfoCard(
                              title: 'Xarid narxi',
                              value: '${product.purchasePrice} UZS',
                              icon: Icons.shopping_cart,
                              color: Colors.blue,
                            ),
                          ),
                        ],
                      ),

                      const SizedBox(height: 12),

                      // Stock Cards
                      Row(
                        children: [
                          Expanded(
                            child: _InfoCard(
                              title: 'Qoldiq',
                              value: '${product.stock} ${product.unit}',
                              icon: Icons.inventory,
                              color: Colors.purple,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: _InfoCard(
                              title: 'Minimal qoldiq',
                              value: '${product.minStock} ${product.unit}',
                              icon: Icons.warning_amber,
                              color: Colors.orange,
                            ),
                          ),
                        ],
                      ),

                      const SizedBox(height: 24),

                      // Details Section
                      const Text(
                        'Tafsilotlar',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),

                      const SizedBox(height: 16),

                      _DetailRow(
                        label: 'Mahsulot kodi (SKU)',
                        value: product.sku,
                      ),

                      if (product.barcode != null)
                        _DetailRow(
                          label: 'Shtrix-kod',
                          value: product.barcode!,
                        ),

                      _DetailRow(
                        label: 'O\'lchov birligi',
                        value: product.unit,
                      ),

                      _DetailRow(
                        label: 'Holat',
                        value: product.active ? 'Faol' : 'Faol emas',
                      ),

                      if (product.updatedAt != null)
                        _DetailRow(
                          label: 'Oxirgi yangilanish',
                          value: _formatDate(product.updatedAt!),
                        ),

                      const SizedBox(height: 24),

                      // Action Buttons
                      FilledButton.icon(
                        onPressed: () =>
                            _showStockAdjustment(context, ref, product),
                        icon: const Icon(Icons.add_circle),
                        label: const Text('Qoldiqni o\'zgartirish'),
                        style: FilledButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),

                      const SizedBox(height: 12),

                      OutlinedButton.icon(
                        onPressed: () =>
                            _viewInventoryHistory(context, product),
                        icon: const Icon(Icons.history),
                        label: const Text('Ombor tarixini ko\'rish'),
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, stack) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, size: 64, color: Colors.red),
              const SizedBox(height: 16),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Text(_readableError(error), textAlign: TextAlign.center),
              ),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: () => ref.invalidate(productProvider(productId)),
                child: const Text('Qayta urinish'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _readableError(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      final code = error.response?.statusCode;
      if (code == 403) {
        if (data is Map &&
            data['error'] is Map &&
            data['error']['code'] == 'subscription_expired') {
          return 'Obuna muddati tugagan. Amalni davom ettirish uchun obunani yangilang.';
        }
        return 'Bu amal uchun ruxsat yo‘q. Hisobingiz va do‘kon huquqlarini tekshiring.';
      }
      if (code == 409) return 'Mahsulot savdo yoki ombor tarixida mavjud. Uni arxivlang.';
      if (code == 401) return 'Sessiya muddati tugagan. Qayta tizimga kiring.';
      if (code == 404)
        return 'Mahsulot topilmadi yoki bu do‘konga tegishli emas.';
      return 'Server bilan bog‘lanishda xatolik yuz berdi. Qayta urinib ko‘ring.';
    }
    return 'Ma’lumotni yuklab bo‘lmadi. Qayta urinib ko‘ring.';
  }

  Widget _buildStockStatusBadge(Product product) {
    Color color;
    IconData icon;
    String label;

    switch (product.stockStatus) {
      case 'tugagan':
        color = Colors.red;
        icon = Icons.error;
        label = 'Tugagan';
        break;
      case 'kam_qolgan':
        color = Colors.orange;
        icon = Icons.warning;
        label = 'Kam qolgan';
        break;
      case 'mavjud':
        color = Colors.green;
        icon = Icons.check_circle;
        label = 'Mavjud';
        break;
      default:
        color = Colors.grey;
        icon = Icons.help;
        label = 'Noma\'lum';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.bold,
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }

  void _showOptionsMenu(BuildContext context, WidgetRef ref) {
    showModalBottomSheet(
      context: context,
      builder: (context) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.archive),
                title: const Text('Arxivlash'),
                onTap: () async {
                  Navigator.pop(context);
                  await _archiveProduct(context, ref);
                },
              ),
              ListTile(
                leading: const Icon(Icons.delete, color: Colors.red),
                title: const Text('O\'chirish',
                    style: TextStyle(color: Colors.red)),
                onTap: () async {
                  Navigator.pop(context);
                  await _deleteProduct(context, ref);
                },
              ),
            ],
          ),
        );
      },
    );
  }

  Future<void> _archiveProduct(BuildContext context, WidgetRef ref) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Mahsulotni arxivlash'),
        content: const Text(
          'Mahsulot arxivlanadi va sotuvda ko\'rinmaydi. Davom etasizmi?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Yo\'q'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Ha, arxivlash'),
          ),
        ],
      ),
    );

    if (confirm == true && context.mounted) {
      try {
        await ref.read(productsProvider.notifier).archiveProduct(productId);

        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Mahsulot arxivlandi'),
              backgroundColor: Colors.green,
            ),
          );
          Navigator.pop(context);
        }
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(_readableError(e)),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    }
  }

  Future<void> _deleteProduct(BuildContext context, WidgetRef ref) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Mahsulotni o\'chirish'),
        content: const Text(
          'Mahsulot butunlay o\'chiriladi. Bu amalni qaytarib bo\'lmaydi. Davom etasizmi?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Yo\'q'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Ha, o\'chirish'),
          ),
        ],
      ),
    );

    if (confirm == true && context.mounted) {
      try {
        await ref.read(productsProvider.notifier).deleteProduct(productId);

        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Mahsulot o\'chirildi'),
              backgroundColor: Colors.green,
            ),
          );
          Navigator.pop(context);
        }
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(_readableError(e)),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    }
  }

  void _showStockAdjustment(
      BuildContext context, WidgetRef ref, Product product) {
    showDialog(
      context: context,
      builder: (context) => _StockAdjustmentDialog(product: product),
    );
  }

  void _viewInventoryHistory(BuildContext context, Product product) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Ombor tarixi tez orada qo\'shiladi'),
      ),
    );
  }

  String _formatDate(DateTime date) {
    return '${date.day}.${date.month}.${date.year} ${date.hour}:${date.minute.toString().padLeft(2, '0')}';
  }
}

class _InfoCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final Color color;

  const _InfoCard({
    required this.title,
    required this.value,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color, size: 24),
            const SizedBox(height: 8),
            Text(
              title,
              style: TextStyle(
                fontSize: 12,
                color: Colors.grey[600],
              ),
            ),
            const SizedBox(height: 4),
            Text(
              value,
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _DetailRow({
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 2,
            child: Text(
              label,
              style: TextStyle(
                color: Colors.grey[600],
                fontSize: 14,
              ),
            ),
          ),
          Expanded(
            flex: 3,
            child: Text(
              value,
              style: const TextStyle(
                fontWeight: FontWeight.w500,
                fontSize: 14,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StockAdjustmentDialog extends ConsumerStatefulWidget {
  final Product product;

  const _StockAdjustmentDialog({required this.product});

  @override
  ConsumerState<_StockAdjustmentDialog> createState() =>
      _StockAdjustmentDialogState();
}

class _StockAdjustmentDialogState
    extends ConsumerState<_StockAdjustmentDialog> {
  final _formKey = GlobalKey<FormState>();
  final _deltaController = TextEditingController();
  final _reasonController = TextEditingController();
  bool _isAdding = true;
  bool _isSaving = false;

  String _readableError(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      final code = error.response?.statusCode;
      if (code == 403) {
        if (data is Map &&
            data['error'] is Map &&
            data['error']['code'] == 'subscription_expired') {
          return 'Obuna muddati tugagan. Amalni davom ettirish uchun obunani yangilang.';
        }
        return 'Bu amal uchun ruxsat yo‘q. Hisobingiz va do‘kon huquqlarini tekshiring.';
      }
      if (code == 401) return 'Sessiya muddati tugagan. Qayta tizimga kiring.';
      if (code == 404)
        return 'Mahsulot topilmadi yoki bu do‘konga tegishli emas.';
      return 'Server bilan bog‘lanishda xatolik yuz berdi. Qayta urinib ko‘ring.';
    }
    return 'Ma’lumotni yuklab bo‘lmadi. Qayta urinib ko‘ring.';
  }

  @override
  void dispose() {
    _deltaController.dispose();
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Qoldiqni o\'zgartirish'),
      content: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Joriy qoldiq: ${widget.product.stock} ${widget.product.unit}',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: SegmentedButton<bool>(
                    segments: const [
                      ButtonSegment(
                        value: true,
                        label: Text('Qo\'shish'),
                        icon: Icon(Icons.add),
                      ),
                      ButtonSegment(
                        value: false,
                        label: Text('Ayirish'),
                        icon: Icon(Icons.remove),
                      ),
                    ],
                    selected: {_isAdding},
                    onSelectionChanged: (Set<bool> selection) {
                      setState(() {
                        _isAdding = selection.first;
                      });
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _deltaController,
              decoration: InputDecoration(
                labelText: 'Miqdor',
                border: const OutlineInputBorder(),
                suffixText: widget.product.unit,
              ),
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              validator: (value) {
                if (value == null || value.trim().isEmpty) {
                  return 'Miqdorni kiriting';
                }
                final delta = double.tryParse(value);
                if (delta == null || delta <= 0) {
                  return 'To\'g\'ri miqdor kiriting';
                }
                return null;
              },
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _reasonController,
              decoration: const InputDecoration(
                labelText: 'Sabab',
                border: OutlineInputBorder(),
                hintText: 'Inventarizatsiya, nosozlik, va h.k.',
              ),
              maxLines: 2,
              validator: (value) {
                if (value == null || value.trim().isEmpty) {
                  return 'Sababni kiriting';
                }
                return null;
              },
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _isSaving ? null : () => Navigator.pop(context),
          child: const Text('Bekor qilish'),
        ),
        FilledButton(
          onPressed: _isSaving ? null : _saveAdjustment,
          child: _isSaving
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Saqlash'),
        ),
      ],
    );
  }

  Future<void> _saveAdjustment() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isSaving = true;
    });

    try {
      final delta = double.parse(_deltaController.text);
      final actualDelta = _isAdding ? delta : -delta;

      await ref.read(apiProvider).adjustStock(
            widget.product.id,
            actualDelta.toString(),
            _reasonController.text.trim(),
          );

      // Lokal yangilaymiz — sahifa qayta yuklanmaydi
      ref.read(productsProvider.notifier).adjustStockLocally(
            widget.product.id,
            actualDelta,
          );
      // productProvider ham yangilansin
      ref.invalidate(productProvider(widget.product.id));

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Row(
            children: [
              const Icon(Icons.check_circle_rounded,
                  color: Colors.white, size: 18),
              const SizedBox(width: 8),
              Text(
                  'Qoldiq ${_isAdding ? "qo\'shildi" : "ayrildi"}: ${delta.toStringAsFixed(1)} ${widget.product.unit}'),
            ],
          ),
          backgroundColor: Colors.green[700],
          behavior: SnackBarBehavior.floating,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          margin: const EdgeInsets.all(16),
        ),
      );

      Navigator.pop(context);
    } catch (e) {
      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(_readableError(e)),
          backgroundColor: Colors.red[700],
          behavior: SnackBarBehavior.floating,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          margin: const EdgeInsets.all(16),
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSaving = false;
        });
      }
    }
  }
}
